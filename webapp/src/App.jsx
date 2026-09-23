import { useCallback } from 'react';
import { CameraStream } from './components/CameraStream';
import { DrivePanel } from './components/DrivePanel';
import { KeymapPanel } from './components/KeymapPanel';
import { StatusPanel } from './components/StatusPanel';
import { DEFAULT_ROBOT_IP } from './constants/commands';
import { useKeyboardControls } from './hooks/useKeyboardControls';
import { useRobot } from './hooks/useRobot';
import { useRobotControl } from './hooks/useRobotControl';

export default function App() {
  const { send, streamUrl, link } = useRobot(DEFAULT_ROBOT_IP);
  const { drive, ledOn, shooting, flashed, driveRef, startMove, releaseMove, doCommand } =
    useRobotControl(send);

  // Keyboard taps reuse the same momentary highlight the mouse taps produce;
  // useRobotControl already sets it, so nothing extra is needed here.
  const noop = useCallback(() => {}, []);

  useKeyboardControls({
    startMove,
    releaseMove,
    doCommand,
    driveRef,
    onKeyActive: noop,
  });

  return (
    <>
      <div className="layout">
        <DrivePanel
          drive={drive}
          ledOn={ledOn}
          shooting={shooting}
          flashed={flashed}
          onPress={startMove}
          onRelease={releaseMove}
          onTap={doCommand}
        />
        <CameraStream streamUrl={streamUrl} />
        <StatusPanel drive={drive} ledOn={ledOn} shooting={shooting} link={link} />
        <KeymapPanel />
      </div>
    </>
  );
}
