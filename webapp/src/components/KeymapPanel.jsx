import { Fragment } from 'react';
import { Panel } from './Panel';

const KEYMAP = [
  { keys: ['W', 'A', 'S', 'D'], desc: 'drive — hold to move, release to stop' },
  { keys: ['⇧ Shift'], desc: 'immediate stop' },
  { keys: ['Q', 'E'], desc: 'light on / off' },
  { keys: ['Space'], desc: 'shoot' },
];

/** Full-width bottom row: what each key does. */
export function KeymapPanel() {
  return (
    <Panel title="Keyboard map" area="keys">
      <div className="keymap">
        {KEYMAP.map((entry, index) => (
          <Fragment key={entry.desc}>
            {index > 0 && <div className="sep" />}
            <div className="item">
              {entry.keys.map((key) => (
                <kbd key={key}>{key}</kbd>
              ))}
              <span className="desc">{entry.desc}</span>
            </div>
          </Fragment>
        ))}
      </div>

      {/* <p className="note">
        This app runs entirely on your laptop — it is not served by the robot. It talks to
        whatever firmware is currently on the ESP32. <code>/go /back /left /right /stop /ledon
        /ledoff</code> already exist on the robot&apos;s current firmware and work now.{' '}
        <code>/shoot</code> only exists after the new firmware is flashed; until then it shows a
        &ldquo;no response&rdquo; link error when pressed — harmless, it just means that route
        doesn&apos;t exist yet.
      </p> */}
    </Panel>
  );
}
