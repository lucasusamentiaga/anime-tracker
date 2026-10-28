## Qué cambia

<!-- Una o dos frases: qué arregla o añade y por qué. Si cierra un issue: "Cierra #123". -->

## Cómo probarlo

<!-- Pasos para verlo funcionando (página, botón, datos de ejemplo). -->

## Comprobaciones

- [ ] `python -m pytest tests/ -q` pasa
- [ ] `ruff check .` sin avisos
- [ ] Si hay textos nuevos en la interfaz, están en `i18n_ui.py` (inglés, francés y alemán)
- [ ] Si cambia algo que ve el usuario, hay una línea en `CHANGELOG.md`
- [ ] Probado también en el móvil (ventana estrecha) si toca la interfaz
