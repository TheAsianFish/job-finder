import respx
from httpx import Response

from opportunity_radar.discovery.token_guess import candidate_tokens, guess_board


def test_candidate_tokens_cover_id_domain_and_name():
    tokens = candidate_tokens("together-ai", "together.ai", "Together AI")
    assert tokens[0] == "together-ai"
    assert "togetherai" in tokens
    assert "together" in tokens
    assert len(tokens) == len(set(tokens)) <= 6


def test_candidate_tokens_handle_short_domains():
    assert "xai" in candidate_tokens("xai", "x.ai")
    assert "x" in candidate_tokens("xai", "x.ai")


@respx.mock
async def test_guess_board_returns_first_non_empty_board(ctx):
    respx.get("https://boards-api.greenhouse.io/v1/boards/xai/jobs").mock(
        return_value=Response(200, json={"jobs": [{"id": 1, "title": "SWE Intern"}]})
    )
    respx.get(url__regex=r"https://api\.ashbyhq\.com/.*").mock(return_value=Response(404))
    respx.get(url__regex=r"https://api\.lever\.co/.*").mock(return_value=Response(404))
    result = await guess_board(ctx, "xai", "x.ai")
    assert result is not None
    assert result.fingerprint.adapter == "greenhouse"
    assert result.fingerprint.config == {"board_token": "xai"}
    assert result.job_count == 1


@respx.mock
async def test_guess_board_ignores_empty_boards(ctx):
    respx.get(url__regex=r"https://boards-api\.greenhouse\.io/.*").mock(
        return_value=Response(200, json={"jobs": []})
    )
    respx.get(url__regex=r"https://api\.ashbyhq\.com/.*").mock(
        return_value=Response(200, json={"jobs": []})
    )
    respx.get(url__regex=r"https://api\.lever\.co/.*").mock(return_value=Response(200, json=[]))
    assert await guess_board(ctx, "quietco", "quietco.com") is None


@respx.mock
async def test_guess_board_falls_through_to_lever_on_later_candidate(ctx):
    respx.get(url__regex=r"https://boards-api\.greenhouse\.io/.*").mock(return_value=Response(404))
    respx.get(url__regex=r"https://api\.ashbyhq\.com/.*").mock(return_value=Response(404))
    respx.get("https://api.lever.co/v0/postings/acme-co?mode=json").mock(return_value=Response(404))
    respx.get("https://api.lever.co/v0/postings/acmeco?mode=json").mock(
        return_value=Response(200, json=[{"id": "a", "text": "Intern"}])
    )
    result = await guess_board(ctx, "acme-co", "acmeco.com")
    assert result is not None
    assert result.fingerprint.adapter == "lever"
    assert result.fingerprint.config == {"site": "acmeco"}
