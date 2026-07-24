local p = {
  bg = "#16242d",
  bg_alt = "#1b2d40",
  fg = "#d6e2ee",
  muted = "#73a6cb",
  accent = "#8bc9eb",
  accent_soft = "#6fb8e3",
  accent_strong = "#b4e4f6",
  select = "#355066",
  white = "#f2fcff",
}

vim.cmd("highlight clear")
vim.o.termguicolors = true
vim.g.colors_name = "dudley-wellness-floor"

local hi = vim.api.nvim_set_hl
hi(0, "Normal", { fg = p.fg, bg = p.bg })
hi(0, "NormalFloat", { fg = p.fg, bg = p.bg_alt })
hi(0, "LineNr", { fg = p.muted, bg = p.bg })
hi(0, "CursorLine", { bg = p.bg_alt })
hi(0, "CursorLineNr", { fg = p.white, bg = p.bg_alt, bold = true })
hi(0, "Comment", { fg = p.muted, italic = true })
hi(0, "Keyword", { fg = p.accent, bold = true })
hi(0, "Function", { fg = p.accent_strong })
hi(0, "String", { fg = "#d1eef8" })
hi(0, "Type", { fg = p.accent_soft })
hi(0, "Identifier", { fg = p.fg })
hi(0, "Visual", { fg = p.white, bg = p.select })
hi(0, "StatusLine", { fg = p.white, bg = p.bg_alt })
hi(0, "Pmenu", { fg = p.fg, bg = p.bg_alt })
hi(0, "PmenuSel", { fg = p.white, bg = p.select })
