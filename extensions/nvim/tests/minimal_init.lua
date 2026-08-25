local here = vim.fn.fnamemodify(vim.fn.resolve(debug.getinfo(1, 'S').source:sub(2)), ':p:h:h')
vim.opt.runtimepath:prepend(here)

local plenary = vim.env.PLENARY or vim.fn.expand('~/.local/share/nvim/site/pack/vendor/start/plenary.nvim')
vim.opt.runtimepath:prepend(plenary)

vim.opt.swapfile = false
vim.cmd('runtime plugin/plenary.vim')
