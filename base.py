"""
Base class for all strategies.
Every strategy file must:
  1. Import and subclass BaseStrategy
  2. Set NAME and DESCRIPTION
  3. Implement render_sidebar(self) and run(self) methods
"""

import streamlit as st

class BaseStrategy:
    NAME = "Unnamed Strategy"
    DESCRIPTION = "No description provided."

    def render_sidebar(self):
        """Render sidebar controls specific to this strategy."""
        raise NotImplementedError

    def run(self):
        """Run the strategy and render results on the main page."""
        raise NotImplementedErrorcd 