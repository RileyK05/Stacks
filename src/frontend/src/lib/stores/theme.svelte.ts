const STORAGE_KEY = 'theme';

type Theme = 'light' | 'dark';

function initialTheme(): Theme {
  if (typeof localStorage === 'undefined') return 'light';
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return typeof matchMedia !== 'undefined' && matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

let theme = $state<Theme>(initialTheme());

export function currentTheme(): Theme {
  return theme;
}

export function toggleTheme(): void {
  theme = theme === 'dark' ? 'light' : 'dark';
}

export function applyTheme(): void {
  document.documentElement.classList.toggle('dark', theme === 'dark');
}

$effect.root(() => {
  applyTheme();
  $effect(() => {
    applyTheme();
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // private mode etc. — theme just won't persist
    }
  });
});
