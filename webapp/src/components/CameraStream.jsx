import { useEffect, useState } from 'react';
import { Panel } from './Panel';

/**
 * Center column: the MJPEG feed.
 *
 * The stream is a plain <img> pointed at the firmware's multipart endpoint --
 * no player library involved, and no CORS requirement, since images are not
 * subject to the same-origin read restrictions that fetch/XHR are.
 */
export function CameraStream({ streamUrl }) {
  const [loaded, setLoaded] = useState(false);

  // Changing the robot IP swaps in a different stream; show the placeholder
  // again until the new one actually renders a frame.
  useEffect(() => {
    setLoaded(false);
  }, [streamUrl]);

  return (
    <Panel title="Camera stream" area="video">
      <img
        // Remounting on URL change discards any half-loaded previous stream.
        key={streamUrl}
        id="stream"
        src={streamUrl}
        alt=""
        style={{ display: loaded ? 'block' : 'none' }}
        onLoad={() => setLoaded(true)}
        onError={() => setLoaded(false)}
      />

      {!loaded && (
        <div className="placeholder">
          <div className="big">Connecting to camera…</div>
          <div>{streamUrl}</div>
        </div>
      )}
    </Panel>
  );
}
