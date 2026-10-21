" Agentainer colors, inspired by Ayu. Black panes and a slate-blue status line.
" Palette: https://github.com/ayu-theme/ayu-colors/blob/master/themes/dark.yaml
" Highlight groups: :help highlight-groups
highlight clear
if exists('syntax_on')
  syntax reset
endif
set background=dark
let g:colors_name = 'agentainer'

highlight Normal       guifg=#bfbdb6 guibg=#000000 gui=NONE
highlight NonText      guifg=#5a6378 guibg=#000000 gui=NONE
highlight EndOfBuffer  guifg=#333333 guibg=#000000 gui=NONE
highlight LineNr       guifg=#5a6378 guibg=#000000 gui=NONE cterm=NONE term=NONE
highlight CursorLineNr guifg=#e6b450 guibg=#141414 gui=bold cterm=bold term=bold
highlight CursorLine   guifg=NONE guibg=#141414 gui=NONE cterm=NONE term=NONE
highlight ColorColumn  guifg=NONE guibg=#202020 gui=NONE
highlight SignColumn   guifg=#5a6378 guibg=#000000 gui=NONE
highlight StatusLine   guifg=#bfbdb6 guibg=#253340 gui=bold cterm=bold term=bold
highlight StatusLineNC guifg=#747474 guibg=#202020 gui=NONE cterm=NONE term=NONE
highlight VertSplit    guifg=#333333 guibg=#000000 gui=NONE cterm=NONE
highlight Visual       guifg=NONE guibg=#333333 gui=NONE
highlight Search       guifg=#000000 guibg=#e6b450 gui=NONE
highlight IncSearch    guifg=#000000 guibg=#ff8f40 gui=bold cterm=bold
highlight MatchParen   guifg=#ffb454 guibg=#333333 gui=bold
highlight Pmenu        guifg=#bfbdb6 guibg=#202020 gui=NONE
highlight PmenuSel     guifg=#000000 guibg=#e6b450 gui=NONE
highlight PmenuSbar    guifg=NONE guibg=#333333 gui=NONE
highlight PmenuThumb   guifg=NONE guibg=#5a6378 gui=NONE
highlight Directory   guifg=#59c2ff guibg=NONE gui=NONE
highlight Title       guifg=#e6b450 guibg=NONE gui=bold
highlight Comment     guifg=#747474 guibg=NONE gui=italic
highlight Constant    guifg=#d2a6ff guibg=NONE gui=NONE
highlight String      guifg=#aad94c guibg=NONE gui=NONE
highlight Identifier  guifg=#59c2ff guibg=NONE gui=NONE cterm=NONE
highlight Function    guifg=#ffb454 guibg=NONE gui=NONE
highlight Statement   guifg=#ff8f40 guibg=NONE gui=NONE cterm=NONE
highlight PreProc     guifg=#ffb454 guibg=NONE gui=NONE
highlight Type        guifg=#59c2ff guibg=NONE gui=NONE cterm=NONE
highlight Special     guifg=#95e6cb guibg=NONE gui=NONE
highlight Underlined  guifg=#59c2ff guibg=NONE gui=underline
highlight Error       guifg=#f07178 guibg=#000000 gui=bold
highlight ErrorMsg    guifg=#f07178 guibg=#000000 gui=bold
highlight WarningMsg  guifg=#e6b450 guibg=#000000 gui=NONE
highlight Todo        guifg=#e6b450 guibg=#202020 gui=bold
highlight SpecialKey  guifg=#5a6378 guibg=NONE gui=NONE
