from msu_anechoic import spec_an
from msu_anechoic import turntable
from msu_anechoic.turntable import AzEl


class Peaking:
    """Class for peaking."""
    def __init__(
        self,
        *
        minimum_az: float,
        maximum_az: float,
        minimum_el: float,
        maximum_el: float,
        spectrum_analyzer: spec_an.SpectrumAnalyzerHP8563E,
        turn_table: turntable.TurnTable,
    ):
        self.minimum_az = minimum_az
        self.maximum_az = maximum_az
        self.minimum_el = minimum_el
        self.maximum_el = maximum_el
        self.spectrum_analyzer = spectrum_analyzer
        self.turn_table = turn_table
        pass

    def box_scan(
        self,
        *,
        azimuth_step_count: int,
        elevation_step_count: int,
    ) -> float:
        """Perform a box scan."""
        azimuth_range = self.maximum_az - self.minimum_az
        elevation_range = self.maximum_el - self.minimum_el

        azimuth_step_size = azimuth_range / azimuth_step_count
        elevation_step_size = elevation_range / elevation_step_count

        best_signal = float('-inf')
        best_az = self.minimum_az
        best_el = self.minimum_el

        for az_step in range(azimuth_step_count + 1):
            for el_step in range(elevation_step_count + 1):
                current_az = self.minimum_az + az_step * azimuth_step_size
                current_el = self.minimum_el + el_step * elevation_step_size

                self.turn_table.move_to(azimuth=current_az, elevation=current_el)
                signal_strength = self.spectrum_analyzer.get_center_frequency_amplitude()

                if signal_strength > best_signal:
                    best_signal = signal_strength
                    best_az = current_az
                    best_el = current_el

        turntable.move_to(AzEl(azimuth=best_az, elevation=best_el))
        return best_signal
        pass
        