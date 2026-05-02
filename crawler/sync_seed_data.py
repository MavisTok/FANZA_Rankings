from storage import sync_seed_data


def main() -> None:
    result = sync_seed_data()
    copied = ", ".join(result["copied"]) or "-"
    repaired = ", ".join(result["repaired_months"]) or "-"
    print(f"[seed] copied={copied} repaired_months={repaired}")


if __name__ == "__main__":
    main()
