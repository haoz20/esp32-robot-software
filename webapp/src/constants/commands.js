/**
 * Single source of truth for robot commands.
 *
 * Each `id` is also the firmware endpoint path: id "go" -> GET /go.
 * These routes are implemented in app_httpd.cpp (startCameraServer).
 */

/** Commands that drive the motors. Held down: press starts, release stops. */
export const DRIVE_COMMANDS = {
  GO: 'go',
  BACK: 'back',
  LEFT: 'left',
  RIGHT: 'right',
};

/** Human-readable drive state, shown in the status panel. */
export const DRIVE_LABELS = {
  [DRIVE_COMMANDS.GO]: 'forward',
  [DRIVE_COMMANDS.BACK]: 'backward',
  [DRIVE_COMMANDS.LEFT]: 'left',
  [DRIVE_COMMANDS.RIGHT]: 'right',
};

export const COMMANDS = {
  ...DRIVE_COMMANDS,
  STOP: 'stop',
  LED_ON: 'ledon',
  LED_OFF: 'ledoff',
  SHOOT: 'shoot',
};

/**
 * Physical-key bindings, keyed by KeyboardEvent.code rather than .key so the
 * bindings follow key *position* and work the same on any keyboard layout.
 */
export const HOLD_KEYS = {
  KeyW: DRIVE_COMMANDS.GO,
  KeyS: DRIVE_COMMANDS.BACK,
  KeyA: DRIVE_COMMANDS.LEFT,
  KeyD: DRIVE_COMMANDS.RIGHT,
};

export const TAP_KEYS = {
  ShiftLeft: COMMANDS.STOP,
  KeyQ: COMMANDS.LED_ON,
  KeyE: COMMANDS.LED_OFF,
  Space: COMMANDS.SHOOT,
};

/** Port the firmware serves the MJPEG stream on (separate httpd instance). */
export const STREAM_PORT = 81;

/** Give up on a command this long after sending it. */
export const REQUEST_TIMEOUT_MS = 2000;

/** How long the "firing" indicator stays lit after a shoot command. */
export const SHOOT_FLASH_MS = 350;

/** How long momentary buttons (stop, light off) stay highlighted when tapped. */
export const TAP_FLASH_MS = 150;

export const DEFAULT_ROBOT_IP = '192.168.4.1';
