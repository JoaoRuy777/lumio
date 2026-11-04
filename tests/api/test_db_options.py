from lumio_api.db import pool_options


def test_pooler_do_neon_desliga_cache_de_prepared_statements():
    url = "postgresql://lumio_app:x@ep-cool-name-123-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require"
    assert pool_options(url) == {"statement_cache_size": 0}


def test_conexao_direta_mantem_o_padrao():
    assert pool_options("postgresql://lumio_app:x@ep-cool-name-123.us-east-2.aws.neon.tech/neondb") == {}
    assert pool_options("postgresql://lumio_app:x@postgres:5432/lumio") == {}
