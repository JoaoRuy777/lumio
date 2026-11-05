// Tema antes da primeira pintura: escolha salva ou, sem escolha, o do sistema.
// Arquivo à parte (e não <script> no HTML) para a política de segurança (CSP)
// poder proibir qualquer script embutido na página.
try {
  var t = localStorage.getItem("lumio-theme");
  if (t !== "light" && t !== "dark") t = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = t;
} catch (e) {}
