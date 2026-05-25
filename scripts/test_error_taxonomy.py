from services.error_types import build_error_record


def main():
    error = ValueError("Pydantic validation failed: invalid JSON")

    record = build_error_record(
        error=error,
        market={
            "id": "00000000-0000-0000-0000-000000000000",
            "external_market_id": "test_market",
            "title": "Test market",
        },
        stage="test",
    )

    print(record)


if __name__ == "__main__":
    main()