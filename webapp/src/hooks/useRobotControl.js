import { useCallback, useEffect, useRef, useState } from 'react';
import { COMMANDS, SHOOT_FLASH_MS, TAP_FLASH_MS } from '../constants/commands';

/**
 * Owns what the robot is currently doing and issues the commands that get it
 * there. UI highlighting is derived from this state rather than being poked
 * onto elements imperatively.
 *
 * @param {(cmd: string) => void} send - from useRobot
 */
export function useRobotControl(send) {
  const [drive, setDrive] = useState(null); // null | 'go' | 'back' | 'left' | 'right'
  const [ledOn, setLedOn] = useState(false);
  const [shooting, setShooting] = useState(false);
  const [flashed, setFlashed] = useState(null); // momentary highlight for tap buttons

  // Mirrors `drive` for reads inside event listeners. State setters are async
  // and the listeners are registered once, so reading `drive` directly there
  // would see a stale value; this ref is always current.
  const driveRef = useRef(null);

  const shootTimer = useRef(null);
  const flashTimer = useRef(null);

  // Timers must not outlive the component, or they fire setState on an
  // unmounted tree.
  useEffect(() => () => {
    clearTimeout(shootTimer.current);
    clearTimeout(flashTimer.current);
  }, []);

  const flash = useCallback((cmd, ms = TAP_FLASH_MS) => {
    setFlashed(cmd);
    clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlashed(null), ms);
  }, []);

  const startMove = useCallback(
    (cmd) => {
      if (driveRef.current === cmd) return; // already moving this way
      driveRef.current = cmd;
      setDrive(cmd);
      send(cmd);
    },
    [send],
  );

  const stopMove = useCallback(() => {
    driveRef.current = null;
    setDrive(null);
    send(COMMANDS.STOP); // sent unconditionally: an extra stop is always safe
  }, [send]);

  const doCommand = useCallback(
    (cmd) => {
      switch (cmd) {
        case COMMANDS.STOP:
          stopMove();
          flash(COMMANDS.STOP);
          break;

        case COMMANDS.LED_ON:
          send(cmd);
          setLedOn(true);
          break;

        case COMMANDS.LED_OFF:
          send(cmd);
          setLedOn(false);
          flash(COMMANDS.LED_OFF);
          break;

        case COMMANDS.SHOOT:
          send(cmd);
          setShooting(true);
          clearTimeout(shootTimer.current);
          shootTimer.current = setTimeout(() => setShooting(false), SHOOT_FLASH_MS);
          break;

        default:
          break;
      }
    },
    [send, stopMove, flash],
  );

  /** Release handler for hold-to-drive controls: only stops if this cmd is the active one. */
  const releaseMove = useCallback(
    (cmd) => {
      if (driveRef.current === cmd) stopMove();
    },
    [stopMove],
  );

  return {
    drive,
    ledOn,
    shooting,
    flashed,
    driveRef,
    startMove,
    stopMove,
    releaseMove,
    doCommand,
  };
}
