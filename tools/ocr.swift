// 이미지의 글자를 macOS 내장 Vision으로 읽어 한 줄씩 출력한다 (인터넷 연결 없이 맥 안에서 처리).
// src/screenshot_runs.py가 처음 쓸 때 swiftc로 컴파일한다.
// 사용법: ocr 이미지경로

import Foundation
import Vision

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("사용법: ocr 이미지경로\n".data(using: .utf8)!)
    exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ko-KR", "en-US"]
request.usesLanguageCorrection = false

do {
    try VNImageRequestHandler(url: URL(fileURLWithPath: CommandLine.arguments[1])).perform([request])
} catch {
    FileHandle.standardError.write("글자를 읽지 못했어요: \(error.localizedDescription)\n".data(using: .utf8)!)
    exit(1)
}
for observation in request.results ?? [] {
    if let text = observation.topCandidates(1).first?.string {
        print(text)
    }
}
