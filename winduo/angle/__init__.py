"""Recovering lid travel from the webcam.

The pieces, in the order a frame moves through them:

``tracker``     one grayscale frame pair to one vertical shift, in pixels.
``estimator``   accumulated shift to degrees of travel from neutral.
``camera``      the camera thread that drives both.
``calibration`` the guided sweep that fits shift to degrees.
``lidswitch``   the operating system's own open/shut signal.
"""

from winduo.angle.estimator import AngleSample, TravelEstimator
from winduo.angle.tracker import TRACK_WIDTH, ShiftReading, ShiftTracker, prepare

__all__ = [
    "TRACK_WIDTH",
    "AngleSample",
    "ShiftReading",
    "ShiftTracker",
    "TravelEstimator",
    "prepare",
]
