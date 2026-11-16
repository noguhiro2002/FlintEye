import { useMediaPaused } from '../hooks/MonitoringContext';
interface WebRtcEmbedProps {
  url: string | null;
  title: string;
}

export function WebRtcEmbed({ url, title }: WebRtcEmbedProps): JSX.Element {
  const paused = useMediaPaused();
  if (paused) return <div className="panel-empty" role="status">Monitoring is stopped or finishing recordings. Start monitoring from Dashboard to watch live video.</div>;
  if (!url) {
    return <div className="panel-empty">Select a stream to open WebRTC viewer.</div>;
  }

  return (
    <div className="webrtc-panel">
      <div className="webrtc-title">{title}</div>
      <iframe
        className="webrtc-frame"
        src={url}
        title={title}
        allow="autoplay; fullscreen; picture-in-picture"
      />
    </div>
  );
}
