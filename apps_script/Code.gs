/**
 * 러닝 기록 수신용 Apps Script 웹 앱.
 *
 * src/upload_sheet.py가 보낸 러닝 기록 중 시트에 없는 기록ID만 '러닝기록' 탭에 추가하고,
 * '월별' 탭을 다시 계산한다. (러닝이 없던 달도 0으로 채움)
 *
 * 설정: 프로젝트 설정(톱니바퀴) → 스크립트 속성 → TOKEN 추가 (.env의 RUNNING_SHEET_TOKEN과 같은 값)
 */

const RUNS_SHEET = '러닝기록';
const MONTHLY_SHEET = '월별';
const HEADERS = ['기록ID', '날짜', '연월', '연도', '요일', '장소', '기기',
                 '거리_km', '시간_분', '페이스_분_km', '페이스_표시', '평균심박'];
// 시트가 숫자·날짜로 자동 변환하지 않도록 텍스트로 고정할 열 (예: 기록ID '12e456…', 연월 '2025-10')
const TEXT_COLUMNS = ['기록ID', '연월', '페이스_표시'];
const MONTHLY_HEADERS = ['연월', '러닝_횟수', '거리_km', '실내_횟수', '실외_횟수', '누적_거리_km'];

function doGet(e) {
  if (!isAuthorized_(e.parameter.token)) return json_({ error: 'unauthorized' });
  const sheet = getRunsSheet_();
  // action=rows: 시트에서 직접 고친 값(예: 평균심박)을 파이썬으로 가져갈 때 사용
  if (e.parameter.action === 'rows') return json_({ rows: readRows_(sheet) });
  return json_({ ids: Array.from(existingIds_(sheet)) });
}

/** 시트의 모든 러닝 기록을 {열 이름: 값} 목록으로. 날짜는 'yyyy-MM-dd' 문자열로 바꾼다. */
function readRows_(sheet) {
  const last = sheet.getLastRow();
  if (last < 2) return [];
  const tz = Session.getScriptTimeZone();
  return sheet.getRange(2, 1, last - 1, HEADERS.length).getValues().map(r => {
    const row = {};
    HEADERS.forEach((h, i) => {
      // 시트에서 읽은 날짜는 instanceof Date 판별이 실패할 수 있어 타입 문자열로 확인한다
      const isDate = Object.prototype.toString.call(r[i]) === '[object Date]';
      row[h] = isDate ? Utilities.formatDate(r[i], tz, 'yyyy-MM-dd') : r[i];
    });
    return row;
  });
}

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (!isAuthorized_(body.token)) return json_({ error: 'unauthorized' });

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const sheet = getRunsSheet_();
    const ids = existingIds_(sheet);
    const newRows = [];
    let skipped = 0;

    (body.rows || []).forEach(run => {
      if (ids.has(run['기록ID'])) {
        skipped++;
        return;
      }
      ids.add(run['기록ID']);
      newRows.push(HEADERS.map(h => toCell_(h, run[h])));
    });

    if (newRows.length) {
      const startRow = sheet.getLastRow() + 1;
      TEXT_COLUMNS.forEach(h => {
        sheet.getRange(startRow, HEADERS.indexOf(h) + 1, newRows.length, 1).setNumberFormat('@');
      });
      sheet.getRange(startRow, HEADERS.indexOf('날짜') + 1, newRows.length, 1).setNumberFormat('yyyy-mm-dd');
      sheet.getRange(startRow, 1, newRows.length, HEADERS.length).setValues(newRows);
      sheet.getRange(2, 1, sheet.getLastRow() - 1, HEADERS.length).sort({ column: 2, ascending: true });
    }

    rebuildMonthly_(sheet);
    return json_({ added: newRows.length, skipped: skipped, total: sheet.getLastRow() - 1 });
  } finally {
    lock.releaseLock();
  }
}

function getRunsSheet_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName(RUNS_SHEET) || ss.insertSheet(RUNS_SHEET);
  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADERS);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function existingIds_(sheet) {
  const last = sheet.getLastRow();
  if (last < 2) return new Set();
  return new Set(sheet.getRange(2, 1, last - 1, 1).getValues().map(r => String(r[0])));
}

function rebuildMonthly_(runsSheet) {
  const ss = runsSheet.getParent();
  const sheet = ss.getSheetByName(MONTHLY_SHEET) || ss.insertSheet(MONTHLY_SHEET);
  sheet.clear();

  const table = [MONTHLY_HEADERS];
  const last = runsSheet.getLastRow();
  if (last >= 2) {
    const col = name => HEADERS.indexOf(name);
    const byMonth = {};
    runsSheet.getRange(2, 1, last - 1, HEADERS.length).getValues().forEach(r => {
      const key = String(r[col('연월')]);
      const s = byMonth[key] || (byMonth[key] = { count: 0, km: 0, indoor: 0, outdoor: 0 });
      s.count++;
      s.km += Number(r[col('거리_km')]) || 0;
      if (r[col('장소')] === '실내') s.indoor++;
      else s.outdoor++;
    });

    const months = Object.keys(byMonth).sort();
    let [y, m] = months[0].split('-').map(Number);
    const [endY, endM] = months[months.length - 1].split('-').map(Number);
    let cumulative = 0;
    while (y < endY || (y === endY && m <= endM)) {
      const key = `${y}-${String(m).padStart(2, '0')}`;
      const s = byMonth[key] || { count: 0, km: 0, indoor: 0, outdoor: 0 };
      cumulative += s.km;
      table.push([key, s.count, round_(s.km, 2), s.indoor, s.outdoor, round_(cumulative, 1)]);
      m++;
      if (m > 12) {
        m = 1;
        y++;
      }
    }
  }

  sheet.getRange(1, 1, table.length, 1).setNumberFormat('@');
  sheet.getRange(1, 1, table.length, MONTHLY_HEADERS.length).setValues(table);
  sheet.setFrozenRows(1);
}

function toCell_(header, value) {
  if (value === null || value === undefined) return '';
  if (header === '날짜') {
    const [y, m, d] = String(value).split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  return value;
}

function isAuthorized_(token) {
  const expected = PropertiesService.getScriptProperties().getProperty('TOKEN');
  return Boolean(expected) && token === expected;
}

function round_(value, digits) {
  const f = Math.pow(10, digits);
  return Math.round(value * f) / f;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
