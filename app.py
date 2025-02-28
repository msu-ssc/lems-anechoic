import datetime
import logging
import random

from rich.logging import RichHandler
from rich.panel import Panel
from textual.app import App
from textual.app import ComposeResult
from textual.containers import Center
from textual.containers import HorizontalGroup
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Button
from textual.widgets import Label
from textual.widgets import ProgressBar
from textual.widgets import RichLog


def pretty_timedelta_str(delta: datetime.timedelta) -> str:
    """Convert a timedelta to a pretty string, like '1d 1h 23m 45s'."""
    days, remainder = divmod(delta.total_seconds(), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days > 0:
        return f"{int(days):,}d {int(hours):,}h {int(minutes):,}m {int(seconds):,}s"
    else:
        if hours > 0:
            return f"{int(hours):,}h {int(minutes):,}m {int(seconds):,}s"
        else:
            return f"{int(minutes):,}m {int(seconds):,}s"


class LoggingConsole(RichLog):
    file = False
    console: Widget

    def print(self, content):
        self.write(content)


class RichLogApp(App):
    def compose(self) -> ComposeResult:
        self.test_done = False

        with Vertical():
            # with Horizontal():
            with HorizontalGroup():
                with Center():
                    with HorizontalGroup():
                        yield Label("TURNTABLE:   ")
                        self.turntable_position_label = Label(f"Position: AZ: [green]-55.5[/]; EL: [yellow]-28.5[/]")
                        yield self.turntable_position_label
                    with HorizontalGroup():
                        yield Label("SPEC AN:     ")
                        self.spec_an_center_freq_label = Label(f"CF: 8,450,000,522 Hz")
                        yield self.spec_an_center_freq_label
                        self.spec_an_span_label = Label(f"SPAN: 1,000 Hz")
                        self.spec_an_span_label.styles.padding = (0, 1)
                        yield self.spec_an_span_label
                        self.spec_an_center_frequency_amplitude_label = Label(f"CF amp: -99 dBm")
                        yield self.spec_an_center_frequency_amplitude_label
                        self.spec_an_peak_amplitude_label = Label(f"Peak amp: -99 dBm")
                        self.spec_an_peak_amplitude_label.styles.padding = (0, 1)
                        yield self.spec_an_peak_amplitude_label
                    with HorizontalGroup():
                        yield Label("SIG GEN:     ")
                        self.sig_gen_status_label = Label(f"<not connected>")
                        yield self.sig_gen_status_label
                    with HorizontalGroup():
                        yield Label("TEST STATUS: ")
                        self.test_start_time_label = Label(f"Began at 12:34:56")
                        self.test_elapsed_time_label = Label(f"Elapsed: 1h 23m 45s")
                        self.test_elapsed_time_label.styles.padding = (0, 1)
                        self.test_remaining_time_label = Label(f"Remaining: 1h 23m 45s")
                        self.test_finish_time_label = Label(f"Finishing at 14:00:00")
                        self.test_finish_time_label.styles.padding = (0, 1)
                        yield self.test_start_time_label
                        yield self.test_elapsed_time_label
                        yield self.test_remaining_time_label
                        yield self.test_finish_time_label

                    with HorizontalGroup():
                        yield Label("This cut:  ")
                        self.this_cut_progress_bar = ProgressBar(total=100)
                        yield self.this_cut_progress_bar
                        self.this_cut_status_label = Label("??? of ??? points in this cut")
                        self.this_cut_progress_bar.styles.padding = (0, 1)
                        yield self.this_cut_status_label
                    with HorizontalGroup():
                        yield Label("Cuts:      ")
                        self.cuts_progress_bar = ProgressBar(total=5)
                        yield self.cuts_progress_bar
                        self.cuts_status_label = Label("??? of ??? cuts in this test")
                        self.cuts_progress_bar.styles.padding = (0, 1)
                        yield self.cuts_status_label
                    with HorizontalGroup():
                        yield Label("All points:")
                        self.all_points_progress_bar = ProgressBar(total=500)
                        yield self.all_points_progress_bar
                        self.all_points_status_label = Label("??? of ??? total points")
                        self.all_points_progress_bar.styles.padding = (0, 1)
                        yield self.all_points_status_label

                # with Center():
                self.emergency_stop_button = Button("EMERGENCY\nSTOP", variant="error")
                self.emergency_stop_button.styles.color = "red"
                # self.emergency_stop_button.styles.border_color = "red"
                yield self.emergency_stop_button

            self.main_content = RichLog(highlight=True, markup=True, wrap=True, auto_scroll=True)
            self.main_content.styles.border = ("round", "white")

            self.debug_log = LoggingConsole(highlight=True, markup=True)
            self.debug_log.styles.border = ("round", "white")
            self.debug_log.border_title = "DEBUG LOG"
            self.debug_log.styles.border_title_align = "center"

            self.logger = logging.getLogger("rich_log_app")
            self.logger.setLevel(logging.DEBUG)
            self.logger.addHandler(
                RichHandler(
                    console=self.debug_log,
                    omit_repeated_times=False,
                    log_time_format="%X",
                    rich_tracebacks=True,
                )
            )

            yield self.main_content
            yield self.debug_log

    def next_point(self) -> None:
        """Main loop"""
        if self.total_point_index >= self.total_points:
            file_name = R"C:/Users/mayo/dev/lems-anechoic/lab_data.csv"
            panel = Panel(f"Test complete.\n\nOutput saved to [link=file://{file_name}]{file_name}[/link]\nTotal time: {pretty_timedelta_str(datetime.datetime.now() - self.test_start_time)}\nTotal points: {self.total_points:,}\nSeconds per point: {((datetime.datetime.now() - self.test_start_time).total_seconds() / self.total_points):.2f}")
            panel.padding = (1, 2)
            self.main_content.write(panel)
            self.test_done = True
            return

        elevations_index = self.total_point_index // len(self.azimuths)
        azimuths_index = self.total_point_index % len(self.azimuths)

        # Top level display stuff
        elapsed_time = datetime.datetime.now() - self.test_start_time
        self.test_elapsed_time_label.update(f"Elapsed: {pretty_timedelta_str(elapsed_time)}")
        self.test_elapsed_time_label.refresh()

        remaining_time = datetime.timedelta(
            seconds=elapsed_time.total_seconds()
            * (self.total_points - self.total_point_index)
            / (self.total_point_index + 1)
        )
        self.test_remaining_time_label.update(f"Remaining: {pretty_timedelta_str(remaining_time)}")
        self.test_remaining_time_label.refresh()

        finish_time = datetime.datetime.now() + remaining_time
        self.test_finish_time_label.update(f"Finishing at {finish_time:%H:%M:%S}")
        self.test_finish_time_label.refresh()

        # Progress bars
        self.all_points_progress_bar.update(progress=self.total_point_index + 1)
        self.this_cut_progress_bar.update(progress=azimuths_index + 1)
        self.cuts_progress_bar.update(progress=elevations_index + 1)

        self.all_points_status_label.update(
            f"{int(self.total_point_index) + 1:,} of {int(self.total_points):,} total points"
        )
        self.all_points_status_label.refresh()

        self.cuts_status_label.update(f"{int(elevations_index) + 1:,} of {len(self.elevations):,} cuts in this test")
        self.cuts_status_label.refresh()

        self.this_cut_status_label.update(f"{int(azimuths_index) + 1:,} of {len(self.azimuths):,} points in this cut")
        self.this_cut_status_label.refresh()

        if azimuths_index == 0:
            if elevations_index != 0:
                cut_time = datetime.datetime.now() - self.cut_start_time

                self.main_content.write(
                    Panel(f"Cut {elevations_index:,} of {len(self.elevations):,} complete\nCut time: {pretty_timedelta_str(cut_time)}")
                )
                self.cut_start_time = datetime.datetime.now()

        # Actual work
        self.main_content.write(
            f"Moving to point {self.total_point_index + 1:,} of {self.total_points:,}: (az={self.azimuths[azimuths_index]:.1f}, el={self.elevations[elevations_index]}:.1f) . . . "
        )
        data = {
            "azimuth": self.azimuths[azimuths_index],
            "elevation": self.elevations[elevations_index],
            "center_amplitude": random.uniform(-100, 0),
            "peak_amplitude": random.uniform(-100, 0),
        }

        self.turntable_position_label.update(
            f"Position: AZ: {data['azimuth'] + random.gauss(0, 0.10):.1f}; EL: {data['elevation'] + random.gauss(0, 0.05):.1f}"
        )
        self.turntable_position_label.refresh()
        self.spec_an_peak_amplitude_label.update(f"Peak amp: {data['peak_amplitude']:.1f} dBm")
        self.spec_an_peak_amplitude_label.refresh()
        self.spec_an_center_frequency_amplitude_label.update(f"CF amp: {data['center_amplitude']:.1f} dBm")
        self.spec_an_center_frequency_amplitude_label.refresh()

        self.main_content.write(
            f"  Measured amplitude at (az={data['azimuth']:.1f}, el={data['elevation']:.1f}): {data['center_amplitude']:.1f} dBm"
        )
        self.total_point_index += 1

        # Tail recursion
        # self.set_timer(0.05, self.next_point)
        self.set_timer(random.uniform(0.5, 1), self.next_point)

    # lol
    def _random_log_messages(self):
        if self.test_done:
            self.logger.info("Test is done, stopping random log messages.")
            return

        for _ in range(random.randint(1, 10)):
            log_levels = [logging.DEBUG] * 20 + [logging.INFO] * 3 + [logging.WARNING, logging.ERROR]
            log_level = random.choice(log_levels)
            log_message = f"{logging.getLevelName(log_level)} Some message, additional info: {random.randint(1, 1000)}"
            if random.random() < 0.3:  # 30% chance to make the message longer
                log_message += " " + ("extra details " * random.randint(5, 20))
            if random.random() < 0.01:
                try:
                    raise ValueError("An example exception for logging")
                except Exception as e:
                    self.logger.exception("An exception occurred: %s", e)
            else:
                self.logger.log(log_level, log_message[: random.randint(50, 200)])
        self.set_timer(random.random() / 10, self._random_log_messages)

    def on_ready(self) -> None:
        """Called  when the DOM is ready."""

        # METADATA STUFF
        self.test_start_time = datetime.datetime.now()
        self.test_start_time_label.update(f"Began at {self.test_start_time:%H:%M:%S}")
        self.test_start_time_label.refresh()

        # GRID
        self.elevations = list(range(-1, 2, 1))
        self.azimuths = list(range(-3, 4, 1))
        self.total_points = len(self.elevations) * len(self.azimuths)
        self.total_point_index = 0

        # Progress bars
        self.all_points_progress_bar.update(total=self.total_points)
        self.this_cut_progress_bar.update(total=len(self.azimuths))
        self.cuts_progress_bar.update(total=len(self.elevations))

        self.cut_start_time = datetime.datetime.now()

        # Start the actual work
        self.set_timer(0.1, self.next_point)
        self._random_log_messages_timer = self.set_timer(0.5, self._random_log_messages)


if __name__ == "__main__":
    app = RichLogApp()
    app.run()
