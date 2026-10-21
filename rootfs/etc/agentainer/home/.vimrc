" Personal editing settings. Option reference: :help options
set nocompatible
set encoding=utf-8
set termguicolors
set background=dark
syntax enable

set number
set cursorline
set laststatus=2
set ruler
set showcmd
set scrolloff=5
set sidescrolloff=5
set wildmenu

set incsearch
set hlsearch
set ignorecase
set smartcase
set showmatch
nnoremap <Esc><Esc> :nohlsearch<CR>

" Four spaces by default. Filetype rules preserve Makefile tabs.
set expandtab
set tabstop=4
set shiftwidth=4
set softtabstop=-1
set autoindent
filetype plugin indent on
augroup agentainer_indent
  autocmd!
  autocmd FileType yaml,json,javascript,typescript,html,css setlocal shiftwidth=2 softtabstop=-1
augroup END

set list
set listchars=tab:>-,trail:.,nbsp:+

" Undo history lives on the persistent home mount.
set undofile
set undodir=~/.vim/undo
for s:directory in ['undo', 'swap', 'backup']
  call mkdir(expand('~/.vim/' . s:directory), 'p', 0700)
endfor
unlet s:directory

colorscheme agentainer

" Cursor restoration, recovery files and navigation.
" See :help last-position-jump, 'directory', 'backupdir' and :Explore.
set directory=~/.vim/swap//
set backupdir=~/.vim/backup//
set backup
set writebackup

augroup agentainer_cursor
  autocmd!
  autocmd BufReadPost *
    \ let last_line = line("'\"")
    \ | if last_line >= 1 && last_line <= line('$') && &buftype ==# ''
    \      && &filetype !~# 'commit' && &filetype !=# 'gitrebase' && !&diff
    \ |   execute "normal! g`\""
    \ | endif
augroup END

" Netrw is included in Vim's runtime packages.
packadd netrw
" A right-hand browser using 25% of the width. See :help netrw-:Lexplore.
nnoremap <leader>e :25Lexplore!<CR>

" Vim bundles EditorConfig support. Project rules override the defaults above.
" https://github.com/vim/vim/tree/master/runtime/pack/dist/opt/editorconfig
packadd editorconfig

" Apply EditorConfig only to named file buffers; its bundled hooks use <afile>.
" Non-bang silent suppresses informational runtime warnings without ignoring errors.
function! s:ApplyEditorConfig() abort
  if !empty(expand('%:p')) && &buftype ==# ''
    silent EditorConfigReload
  endif
endfunction
augroup editorconfig
  autocmd!
  autocmd BufReadPost,BufNewFile,BufFilePost,VimEnter * call <SID>ApplyEditorConfig()
augroup END
