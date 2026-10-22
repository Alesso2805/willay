"""SPEC's Rímac scenario, told as it happens.

`make demo` clears the demo organization's operational data, runs the `rimac`
simulator scenario against the API and narrates the incidents' timelines until level 2
acknowledges both incidents (PASS) or the story goes wrong (FAIL). The public demo
plays the same story from a dashboard button through the demo worker, and restores the
organization every night.
"""
