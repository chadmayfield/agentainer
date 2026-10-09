# ~/.profile: executed by the command interpreter for login shells.
# Seeded once by AgentBox from Ubuntu's /etc/skel/.profile, with one change: personal
# bin directories go at the end of PATH, so they never shadow the image's tools.

# if running bash
if [ -n "$BASH_VERSION" ]; then
	# include .bashrc if it exists
	if [ -f "$HOME/.bashrc" ]; then
		. "$HOME/.bashrc"
	fi
fi

if [ -d "$HOME/bin" ]; then
	PATH="$PATH:$HOME/bin"
fi
if [ -d "$HOME/.local/bin" ]; then
	PATH="$PATH:$HOME/.local/bin"
fi
