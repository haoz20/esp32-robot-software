import { DRIVE_LABELS } from '../constants/commands';
import { Panel } from './Panel';

function StatusRow({ label, value, tone }) {
  return (
    <div className="stat">
      <span className={`dot ${tone ?? ''}`.trim()} />
      <span className="label">{label}</span>
      <span className="val">{value}</span>
    </div>
  );
}

const LINK_DISPLAY = {
  unknown: { value: 'unknown', tone: 'warn' },
  connected: { value: 'connected', tone: 'on' },
  offline: { value: 'no response', tone: 'off' },
};

/** Right column: live readout of what the robot is doing. */
export function StatusPanel({ drive, ledOn, shooting, link }) {
  const linkState = LINK_DISPLAY[link] ?? LINK_DISPLAY.unknown;

  return (
    <Panel title="Status" area="status">
      <div className="status">
        <StatusRow
          label="Drive"
          value={drive ? DRIVE_LABELS[drive] : 'idle'}
          tone={drive ? 'on' : ''}
        />
        <StatusRow label="Light" value={ledOn ? 'on' : 'off'} tone={ledOn ? 'on' : ''} />
        <StatusRow
          label="Shoot"
          value={shooting ? 'firing' : 'ready'}
          tone={shooting ? 'fire' : ''}
        />
        <StatusRow label="Link" value={linkState.value} tone={linkState.tone} />
      </div>
    </Panel>
  );
}
