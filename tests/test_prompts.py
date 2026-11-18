import prompts


def test_confirmacion_distingue_si_afirmativo_de_si_condicional():
    for yes in ("sí", "Si, búscalo", "vale", "ok por favor", "sí por favor busca fuera", "dale", "vale gracias"):
        assert prompts.is_confirmation(yes), yes
    for no in ("no", "¿qué es BM25?", "si no lo encuentras dime", "sí pero solo en docs", "", "sí " * 8):
        assert not prompts.is_confirmation(no), no


def test_origen_por_etiqueta_de_primera_linea():
    assert prompts.origin_of(prompts.TAG_INTERNAL + "\nx") == "internal"
    assert prompts.origin_of(prompts.TAG_PARTIAL + "\nx") == "partial"     # no se confunde con 'internal'
    assert prompts.origin_of(prompts.TAG_NONE + "\nx") == "none"
    assert prompts.origin_of(prompts.TAG_EXTERNAL + "\nx") == "external"
    assert prompts.origin_of(prompts.TAG_MEMORY + "\nx") == "memory"
    assert prompts.origin_of("texto sin etiqueta\n" + prompts.TAG_INTERNAL) == ""   # solo cuenta la primera linea


def test_oferta_externa_y_prompts():
    reply = prompts.TAG_NONE + "\nNo está.\n\n" + prompts.OFFER_EXTERNAL
    assert prompts.offered_external(reply) and not prompts.offered_external(prompts.TAG_INTERNAL + "\nx")
    p = prompts.build_internal("", "[a.pdf · pág. 1]\ntexto", "")
    assert prompts.TAG_INTERNAL in p and prompts.OFFER_EXTERNAL in p and "[a.pdf · pág. 1]" in p
    ext = prompts.build_external("¿capital de Australia?", reply)
    assert prompts.TAG_EXTERNAL in ext and "¿capital de Australia?" in ext
    assert "NECESITO" in prompts.build_memory("recuerdo", "NECESITO_DOCUMENTOS")
    assert set(prompts.prompt_view()) >= {"internal", "external", "memory", "tags", "offer"}
