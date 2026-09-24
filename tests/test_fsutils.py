from uji_sync.fsutils import folder_subpath, pluginfile_filename, pluginfile_key, safe_name


def test_safe_name_windows_invalid_chars():
    assert safe_name('Tema 1: "Intro" / Parte?') == "Tema 1_ _Intro_ _ Parte_"
    assert safe_name("  nombre.  ") == "nombre"
    assert safe_name("") == "sin nombre"


def test_safe_name_reserved_and_length():
    assert safe_name("CON") == "_CON"
    assert safe_name("nul.txt") == "_nul.txt"
    long = "a" * 200 + ".pdf"
    out = safe_name(long)
    assert len(out) == 80 and out.endswith(".pdf")


def test_pluginfile_key_ignores_revision_and_query():
    a = "https://av/pluginfile.php/55/mod_resource/content/3/Tema%201.pdf?forcedownload=1"
    b = "https://av/pluginfile.php/55/mod_resource/content/4/Tema%201.pdf"
    assert pluginfile_key(a) == pluginfile_key(b) == "pluginfile:55/mod_resource/content/Tema 1.pdf"
    assert pluginfile_filename(a) == "Tema 1.pdf"


def test_folder_subpath():
    url = "https://av/pluginfile.php/9/mod_folder/content/2/Prácticas/P1/enunciado.pdf"
    assert folder_subpath(url) == ["Prácticas", "P1"]
    assert folder_subpath("https://av/pluginfile.php/9/mod_folder/content/2/a.pdf") == []
    # Archivos sin revisión (p. ej. en etiquetas) conservan su ruta completa como clave
    assert pluginfile_key("https://av/pluginfile.php/7/mod_label/intro/x.pdf") == \
        "pluginfile:7/mod_label/intro/x.pdf"
