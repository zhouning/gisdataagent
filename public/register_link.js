// Inject a "Register" link on the Chainlit login page
(function () {
  function addRegisterLink() {
    var form = document.querySelector('form');
    if (!form) return false;
    if (document.getElementById('register-link')) return true;
    var link = document.createElement('div');
    link.id = 'register-link';
    link.style.textAlign = 'center';
    link.style.marginTop = '16px';
    link.innerHTML =
      '<a href="/register" style="color:#6366f1;text-decoration:none;font-size:14px;">' +
      '没有账号？点击注册</a>';
    form.parentNode.insertBefore(link, form.nextSibling);
    return true;
  }
  var attempts = 0;
  var timer = setInterval(function () {
    if (addRegisterLink() || ++attempts > 50) clearInterval(timer);
  }, 200);
})();
