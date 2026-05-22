from services.supabase_service import (
    test_supabase_connection,
    insert_test_pipeline_run,
)


def main():
    print("Probando conexión con Supabase...")

    connection_result = test_supabase_connection()
    print("Conexión OK:")
    print(connection_result)

    print("Probando insert en pipeline_runs...")

    insert_result = insert_test_pipeline_run()
    print("Insert OK:")
    print(insert_result)


if __name__ == "__main__":
    main()