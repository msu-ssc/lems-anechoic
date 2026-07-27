# Threaded Turntable Controller

`msu_anechoic.turntable2` is the non-blocking turntable interface. It uses one
thread to frame incoming serial messages and a second thread to maintain
controller state and send commands.

```python
import time

from msu_anechoic import turntable2


with turntable2.find() as turntable:
    turntable.set_position(azimuth=0, elevation=0)
    turntable.move_to(azimuth=30, elevation=10)

    while turntable.current_state() != turntable2.TurntableState.STOPPED:
        event = turntable.most_recent_event(kind="position")
        if event is not None:
            print(
                f"{event.timestamp}, "
                f"az={event.azimuth}, el={event.elevation}"
            )
        time.sleep(0.5)

    print(f"Finished moving. Final position = {turntable.current_position()}")
```

`set_position`, `move_to`, and `abort` queue work and return immediately.
Commands are processed in order. `move_to` accepts absolute angles and handles
elevation-regime changes internally.

The observable states are:

- `NOT_SET`: communication is working, but the position has not been set.
- `STOPPED`: the table has been set and is not moving.
- `MOVING`: a move, including any elevation-regime transition, is active.
- `NO_COMMUNICATION`: no valid position has arrived before the communication
  timeout.
- `TIMED_OUT`: a SET or MOV operation exceeded its deadline and was aborted.
- `ERROR`: a serial write or controller operation failed.
- `CLOSED`: `close()` has stopped the controller.

Every received line becomes an immutable, hashable `ReceivedMessage`.
Successfully parsed position lines become `ReceivedMessagePosition` events.
Position events exposed by `Turntable` contain absolute elevations after the
current elevation-regime offset has been applied.
