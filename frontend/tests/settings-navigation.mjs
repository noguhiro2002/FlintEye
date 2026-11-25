export async function chooseSettingsCategory(page, name, { advanced = true } = {}) {
  const level = page.getByRole('group', { name: 'Settings level' });
  const modern = await level.isVisible();
  if (modern) {
    const toggle = level.getByRole('button', { name: advanced ? 'Advanced' : 'Basic', exact: true });
    if (await toggle.getAttribute('aria-pressed') !== 'true') await toggle.click();
  }
  const label = !modern && name === 'Runtime JSON' ? 'Advanced' : name;
  const categories = page.getByRole('complementary', { name: 'Settings categories' });
  const select = categories.getByRole('combobox', { name: 'Settings category' });
  if (modern && await select.isVisible()) {
    await select.selectOption({ label });
  } else {
    await categories.getByRole('button', { name: label, exact: true }).click();
  }
}

export async function chooseIpCamera(page, value) {
  const selector = page.getByRole('combobox', { name: 'IP camera to configure' });
  if (await selector.isVisible()) await selector.selectOption(value);
}
