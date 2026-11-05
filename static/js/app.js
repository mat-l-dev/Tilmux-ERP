/* Autocompletar formularios cuando el control lo pide. */
document.addEventListener("change", (event) => {
  const control = event.target;
  if (control instanceof HTMLElement && control.matches("[data-autosubmit]")) {
    const form = control.closest("form");
    if (form) form.submit();
  }
});
