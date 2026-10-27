"""Validation for the standard OpenCV pinhole calibration model."""
import numpy as np

def validate_calibration(K, dist):
    if K.shape != (3, 3) or not np.isfinite(K).all():
        raise ValueError('K must be a finite 3x3 camera matrix.')
    if K[0, 0] <= 0 or K[1, 1] <= 0 or not np.allclose(K[2], [0, 0, 1]):
        raise ValueError('K must have positive focal lengths and last row [0, 0, 1].')
    if dist.size not in (4, 5, 8, 12, 14) or not np.isfinite(dist).all():
        raise ValueError('dist must contain 4, 5, 8, 12, or 14 finite standard OpenCV distortion coefficients.')

