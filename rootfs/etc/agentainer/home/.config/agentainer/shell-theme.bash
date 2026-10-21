# Agentainer colors, inspired by Ayu. Amber user, blue host and gray path.
# Bash prompt escapes: https://www.gnu.org/software/bash/manual/html_node/Controlling-the-Prompt.html
PS1='\[\e[38;2;230;180;80m\]\u\[\e[38;2;89;194;255m\]@\h\[\e[0m\]:\[\e[1;38;2;191;189;182m\]\w\[\e[0m\] \[\e[38;2;230;180;80m\]\$\[\e[0m\] '

# ls uses these styles for directories, links, executables and special files.
export LS_COLORS='rs=0:di=01;38;2;191;189;182:ln=38;2;230;180;80:ex=38;2;170;217;76:pi=38;2;230;180;80:so=38;2;230;180;80:bd=38;2;230;180;80:cd=38;2;230;180;80:or=01;38;2;240;113;120:mi=01;38;2;240;113;120:su=37;41:sg=30;43:tw=30;42:ow=34;42:st=37;44'
