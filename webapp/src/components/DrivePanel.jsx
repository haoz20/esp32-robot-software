import { COMMANDS } from '../constants/commands';
import { ControlButton } from './ControlButton';
import { Panel } from './Panel';

/** Left column: d-pad, light controls, shoot. */
export function DrivePanel({ drive, ledOn, shooting, flashed, onPress, onRelease, onTap }) {
  const holdProps = { hold: true, onPress, onRelease };

  return (
    <Panel title="Drive" area="drive">
      <div className="pad">
        <div className="slot" />
        <ControlButton
          cmd={COMMANDS.GO}
          label="Forward"
          glyph="▲"
          badge="W"
          active={drive === COMMANDS.GO}
          {...holdProps}
        />
        <div className="slot" />

        <ControlButton
          cmd={COMMANDS.LEFT}
          label="Left"
          glyph="◀"
          badge="A"
          active={drive === COMMANDS.LEFT}
          {...holdProps}
        />
        <ControlButton
          cmd={COMMANDS.STOP}
          label="Stop"
          glyph="■"
          badge="⇧"
          variant="stop"
          active={flashed === COMMANDS.STOP}
          onTap={onTap}
        />
        <ControlButton
          cmd={COMMANDS.RIGHT}
          label="Right"
          glyph="▶"
          badge="D"
          active={drive === COMMANDS.RIGHT}
          {...holdProps}
        />

        <div className="slot" />
        <ControlButton
          cmd={COMMANDS.BACK}
          label="Backward"
          glyph="▼"
          badge="S"
          active={drive === COMMANDS.BACK}
          {...holdProps}
        />
        <div className="slot" />
      </div>

      <div className="row">
        <ControlButton
          cmd={COMMANDS.LED_ON}
          label="Light ON"
          badge="Q"
          active={ledOn}
          onTap={onTap}
        />
        <ControlButton
          cmd={COMMANDS.LED_OFF}
          label="Light OFF"
          badge="E"
          active={flashed === COMMANDS.LED_OFF}
          onTap={onTap}
        />
        <ControlButton
          cmd={COMMANDS.SHOOT}
          label="🎯 Shoot"
          badge="Space"
          variant="shoot"
          className="wide"
          active={shooting}
          onTap={onTap}
        />
      </div>
    </Panel>
  );
}
