export function autoGrowTextarea(node: HTMLTextAreaElement, value: unknown) {
  let destroyed = false;
  let parentWidth = node.parentElement?.getBoundingClientRect().width;

  const resize = () => {
    node.style.height = 'auto';
    const styles = getComputedStyle(node);
    const borders = parseFloat(styles.borderTopWidth) + parseFloat(styles.borderBottomWidth);
    const padding = parseFloat(styles.paddingTop) + parseFloat(styles.paddingBottom);
    const height = styles.boxSizing === 'border-box' ? node.scrollHeight + borders : node.scrollHeight - padding;
    node.style.height = `${height}px`;
  };

  node.addEventListener('input', resize);
  const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width;
    if (width !== undefined && width !== parentWidth) {
      parentWidth = width;
      resize();
    }
  });
  if (node.parentElement) observer?.observe(node.parentElement);
  resize();

  return {
    update(nextValue: unknown) {
      if (nextValue !== value) {
        value = nextValue;
        queueMicrotask(() => {
          if (!destroyed) resize();
        });
      }
    },
    destroy() {
      destroyed = true;
      node.removeEventListener('input', resize);
      observer?.disconnect();
    },
  };
}
