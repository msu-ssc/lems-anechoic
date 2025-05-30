# Driver code for issue #8

from msu_ssc import ssc_log

ssc_log.init(level="DEBUG")

from msu_anechoic.turn_table import Turntable

tt = Turntable.find(
    logger=ssc_log.logger,
    show_move_debug=True,
)

tt.interactively_center()