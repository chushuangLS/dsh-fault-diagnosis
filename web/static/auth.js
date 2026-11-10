const form = document.getElementById('account');
const message = document.getElementById('message');
if (new URLSearchParams(location.search).has('registered')) {
  message.textContent = '注册成功，请登录。';
}
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button');
  const register = form.dataset.register === 'yes';
  button.disabled = true;
  message.textContent = '';
  try {
    const response = await fetch(register ? '/api/auth/register' : '/api/auth/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': form.dataset.csrf},
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    const data = await response.json();
    if (!response.ok) {
      message.textContent = data.error || '请求失败，请重试。';
      return;
    }
    location.replace(register ? '/login?registered=1' : '/');
  } catch {
    message.textContent = '连接失败，请重试。';
  } finally {
    button.disabled = false;
  }
});
