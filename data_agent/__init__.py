"""data_agent package."""

from .adk_compat import configure_proj_data_dir, install_adk_warning_filters

install_adk_warning_filters()
configure_proj_data_dir()
