/**
 * One control. Two behaviours:
 *  - hold: press starts the command, release stops it (used for driving)
 *  - tap:  fires once on click (light, shoot, stop)
 *
 * `active` is passed in from derived state rather than tracked internally, so
 * the keyboard and the mouse light up the exact same element.
 */
export function ControlButton({
  cmd,
  label,
  glyph,
  badge,
  hold = false,
  active = false,
  variant,
  className = '',
  onPress,
  onRelease,
  onTap,
}) {
  const classes = ['ctl', variant, className, active ? 'active' : ''].filter(Boolean).join(' ');

  const holdHandlers = hold
    ? {
        onMouseDown: (e) => {
          e.preventDefault();
          onPress?.(cmd);
        },
        onMouseUp: (e) => {
          e.preventDefault();
          onRelease?.(cmd);
        },
        // Dragging off a held button must also release it, otherwise the robot
        // keeps driving with no button visibly pressed.
        onMouseLeave: () => onRelease?.(cmd),
        onTouchStart: (e) => {
          e.preventDefault();
          onPress?.(cmd);
        },
        onTouchEnd: (e) => {
          e.preventDefault();
          onRelease?.(cmd);
        },
      }
    : { onClick: () => onTap?.(cmd) };

  return (
    <button type="button" className={classes} {...holdHandlers}>
      {glyph && <span className="glyph">{glyph}</span>}
      {label}
      <span className="badge">{badge}</span>
    </button>
  );
}
