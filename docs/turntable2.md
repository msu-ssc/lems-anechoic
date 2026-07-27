# Threaded Turntable Controller

`msu_anechoic.turntable2` is the non-blocking turntable interface. It uses one
thread to frame incoming serial messages and a second thread to maintain
controller state and send commands.

```python
import time

from msu_anechoic import turntable2


with turntable2.find() as turntable:
    turntable.set_position(pan=0, tilt=0)
    turntable.move_to(pan=30, tilt=10)

    while turntable.current_state() != turntable2.TurntableState.STOPPED:
        snapshot = turntable.get_complete_state()
        event = snapshot.most_recent_position_event
        position = snapshot.corrected_position
        if event is not None and position is not None:
            print(
                f"{event.timestamp}, "
                f"yaw={event.yaw}, pitch={event.pitch}, "
                f"pan={position.pan}, tilt={position.tilt}"
            )
        time.sleep(0.5)

    print(f"Finished moving. Final position = {turntable.current_position()}")
```

`set_position` and `move_to` queue work and return immediately. Commands are
processed in order. `move_to` accepts physical pan and tilt angles and handles
tilt-regime changes internally. `abort` is the exception: it immediately
invalidates the active operation and every queued command, writes the stop
command, and returns only after that write has been attempted.

## Coordinate terminology

`turntable2` deliberately distinguishes two coordinate layers:

- **Yaw and pitch** are the relative numbers maintained and reported by the
  turntable firmware. A SET command resets both to zero. Raw
  `ReceivedMessagePosition` events therefore expose `yaw` and `pitch`.
- **Pan and tilt** are physical, regime-compensated angles. Public command
  arguments and `current_position()` use `pan` and `tilt`.

The firmware's USB command format is fixed and continues to place these values
in its historical azimuth/elevation slots. That wire format does not change.

## Complete diagnostic state

`get_complete_state()` returns an immutable `TurntableCompleteState` captured
under the controller lock. It includes:

- `uncorrected_position`: the latest raw `YawPitch`;
- `corrected_position`: the latest regime-compensated `PanTilt`;
- `current_regime` and the two-axis `regime_offset`;
- `most_recent_position_event` and `most_recent_event`;
- `state`, `activity`, its detailed `activity_phase`, and `has_been_set`;
- the active operation's corrected `target_position`, `internal_target`, and
  timezone-aware `activity_timeout_at`;
- `last_communication_at`, elapsed communication time, the configured
  communication timeout, queue depth, whether the initial SET is pending,
  position-history and event counts, and the latest asynchronous error.

For example:

```python
snapshot = turntable.get_complete_state()
print(f"firmware: {snapshot.uncorrected_position}")
print(f"physical: {snapshot.corrected_position}")
print(f"offset: {snapshot.regime_offset}")
print(f"timeout: {snapshot.activity_timeout_at}")
```

The observable states are:

- `NOT_SET`: communication is working, but the position has not been set.
- `STOPPED`: the table has been set and is not moving.
- `MOVING`: a move, including any tilt-regime transition, is active.
- `NO_COMMUNICATION`: no valid position has arrived before the communication
  timeout.
- `TIMED_OUT`: a SET or MOV operation exceeded its deadline and was aborted.
- `ERROR`: a serial write or controller operation failed.
- `CLOSED`: `close()` has stopped the controller.

Every received line becomes an immutable, hashable `ReceivedMessage`.
Successfully parsed position lines become `ReceivedMessagePosition` events.
These events intentionally preserve raw firmware yaw and pitch. Use
`current_position()` or `get_complete_state().corrected_position` for physical
pan and tilt.

`position_history()` returns bounded `PositionSample` records containing the
raw `YawPitch` and corrected `PanTilt` observed at each position-event
timestamp. The web monitor uses these paired samples so its two coordinate
plots always describe the same observations.
