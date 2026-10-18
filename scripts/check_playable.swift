// Ask AVFoundation (what QuickTime Player uses) whether each file can be played and its video decoded.
import AVFoundation
import Foundation

let sema = DispatchSemaphore(value: 0)
Task {
    for path in CommandLine.arguments.dropFirst() {
        let asset = AVURLAsset(url: URL(fileURLWithPath: path))
        do {
            let playable = try await asset.load(.isPlayable)
            let tracks = try await asset.loadTracks(withMediaType: .video)
            var decodable = false
            if let track = tracks.first {
                decodable = try await track.load(.isDecodable)
            }
            let audioTracks = try await asset.loadTracks(withMediaType: .audio)
            var audioDecodable = "none"
            if let track = audioTracks.first {
                audioDecodable = "\(try await track.load(.isDecodable))"
            }
            // Try to actually decode a frame.
            let gen = AVAssetImageGenerator(asset: asset)
            var frame = "no"
            do {
                let (img, _) = try await gen.image(at: CMTime(seconds: 1, preferredTimescale: 600))
                frame = "\(img.width)x\(img.height)"
            } catch { frame = "FAILED (\(error.localizedDescription))" }
            print("\((path as NSString).lastPathComponent): playable=\(playable) videoDecodable=\(decodable) audioDecodable=\(audioDecodable) frameAt1s=\(frame)")
        } catch {
            print("\((path as NSString).lastPathComponent): error \(error)")
        }
    }
    sema.signal()
}
sema.wait()
