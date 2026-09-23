import { useEffect } from 'react';
import { COMMANDS, HOLD_KEYS, TAP_KEYS } from '../constants/commands';

/** True while the user is typing into a field, so WASD shouldn't drive the robot. */
function isTyping() {
  const el = document.activeElement;
  if (!el) return false;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable;
}

/**
 * Binds the physical keyboard to the robot. Listeners go on `window` so they
 * work without the page having focus on any particular element.
 *
 * All handlers come from useRobotControl and are referentially stable, so this
 * effect registers once and tears down cleanly on unmount.
 */
export function useKeyboardControls({ startMove, releaseMove, doCommand, driveRef, onKeyActive }) {
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (isTyping()) return;

      const hold = HOLD_KEYS[event.code];
      const tap = TAP_KEYS[event.code];
      if (!hold && !tap) return;

      event.preventDefault(); // stops Space from scrolling the page
      if (event.repeat) return; // one command per physical press, not per repeat

      if (hold) {
        startMove(hold);
      } else {
        doCommand(tap);
        onKeyActive?.(tap, true);
      }
    };

    const handleKeyUp = (event) => {
      const hold = HOLD_KEYS[event.code];
      if (hold) {
        event.preventDefault();
        releaseMove(hold);
        return;
      }

      const tap = TAP_KEYS[event.code];
      // Stop keeps its own momentary flash; the rest clear on release.
      if (tap && tap !== COMMANDS.STOP) onKeyActive?.(tap, false);
    };

    // Safety: if the window loses focus mid-press we never see the keyup, so
    // the robot would keep driving. Stop it.
    const handleBlur = () => {
      if (driveRef.current) releaseMove(driveRef.current);
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
    };
  }, [startMove, releaseMove, doCommand, driveRef, onKeyActive]);
}
