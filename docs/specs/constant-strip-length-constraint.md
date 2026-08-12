# Constant Strip-Length Constraint

This phase adds a visual centerline inextensibility constraint to generated flower-sequence candidates.

For every generated stage, the discrete centerline arc length is projected to the final target profile's canonical centerline length. Open paths use segment-length tangent projection, preserving the target material-coordinate segment lengths while retaining the predicted stage directions. Closed contours use perimeter-preserving projection because an open flat-strip topology cannot be continuously represented as a closed contour without a topology change.

The private CLRSG model remains compatible with the baseline on which it was trained: learned residuals are applied to the legacy unconstrained baseline geometry first, and the constant-length projection is applied afterward. This avoids silently changing the residual reference frame of the approved model.

Candidate and per-pass provenance report the target length, measured length, relative error, projection method, and tolerance. Exports contain the constrained geometry.

This is a visual geometry constraint only. It does not model neutral-axis shift, thinning, plastic strain, springback, tooling contact, roll forces, material constitutive behavior, manufacturability, or production approval.
