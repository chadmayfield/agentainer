# Interactive defaults. Bash options: https://www.gnu.org/software/bash/manual/
case $- in
*i*) ;;
*) return ;;
esac

# Preserve Ubuntu's aliases, completion hooks and less integration.
if [ -r /etc/skel/.bashrc ]; then
	. /etc/skel/.bashrc
fi

HISTCONTROL=ignoreboth
HISTSIZE=5000
HISTFILESIZE=10000
shopt -s histappend checkwinsize
export EDITOR="${EDITOR:-vim}"
export VISUAL="${VISUAL:-$EDITOR}"
export PAGER="${PAGER:-less}"
export LESS="${LESS:-FRX}"

if [ -r "$HOME/.config/agentainer/shell-theme.bash" ]; then
	# shellcheck source=rootfs/etc/agentainer/home/.config/agentainer/shell-theme.bash
	. "$HOME/.config/agentainer/shell-theme.bash"
fi

# Git ships this standalone completion script with its Debian package.
if ! declare -F __git_complete >/dev/null && [ -r /usr/share/bash-completion/completions/git ]; then
	. /usr/share/bash-completion/completions/git
fi
# fzf --help documents --bash and FZF_DEFAULT_OPTS_FILE.
export FZF_DEFAULT_OPTS_FILE="${FZF_DEFAULT_OPTS_FILE:-$HOME/.config/fzf/config}"
if command -v fzf >/dev/null && ! declare -F fzf-file-widget >/dev/null; then
	eval "$(fzf --bash)"
fi

alias ..='cd ..'
alias ...='cd ../..'
alias v='vim'
