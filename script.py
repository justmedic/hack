import asyncio
import aiodns
import sys
import multiprocessing
from multiprocessing import Process, cpu_count
import aiofiles
import itertools
import socket


def generate_subdomains(length, domain_name, include_dash=True):
    """Генерация поддоменов"""
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    if include_dash:
        chars += "-"
    chars = tuple(chars)
    return (
        f"{''.join(sub)}.{domain_name}"
        for sub in itertools.product(chars, repeat=length)
        if not (sub[0] == "-" or sub[-1] == "-")
    )


async def validate_subdomain(resolver, subdomain, semaphore, result_queue):
    """Асинхронная проверка поддомена через DNS-запрос"""
    async with semaphore:
        try:
            await resolver.gethostbyname(subdomain, socket.AF_INET)
            await result_queue.put(subdomain)
        except Exception:
            pass  # Поддомен недоступен


async def writer(result_queue, output_file):
    """Асинхронный писатель для записи результатов в файл"""
    async with aiofiles.open(output_file, "a") as f:
        while True:
            subdomain = await result_queue.get()
            if subdomain is None:
                break
            await f.write(subdomain + "\n")
            result_queue.task_done()


async def worker(subdomains, max_concurrent_requests, result_queue, output_file):
    resolver = aiodns.DNSResolver()
    semaphore = asyncio.Semaphore(max_concurrent_requests)
    writer_task = asyncio.create_task(writer(result_queue, output_file))
    tasks = []
    for subdomain in subdomains:
        task = asyncio.create_task(validate_subdomain(resolver, subdomain, semaphore, result_queue))
        tasks.append(task)
    await asyncio.gather(*tasks)
    await result_queue.put(None)
    await writer_task


def worker_process(subdomains, max_concurrent_requests, output_file):
    """Функция, запускаемая в каждом дочернем процессе"""
    if sys.platform.startswith("win"):
        # Установка политики цикла событий для Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    # Создание новой очереди для этого процесса
    result_queue = asyncio.Queue()
    asyncio.run(worker(subdomains, max_concurrent_requests, result_queue, output_file))


def split_iterable(iterable, n):
    """Разделить генератор на n частей"""
    from itertools import islice

    it = iter(iterable)
    while True:
        chunk = list(islice(it, n))
        if not chunk:
            break
        yield chunk


def main():
    domain = input("Введите доменное имя (example.com): ").strip()
    length = int(input("Введите длину поддомена (например, 2 или 3): "))
    include_dash_input = input("Учитывать символ '-'? (yes/no): ").strip().lower()
    include_dash = include_dash_input == "yes"
    max_concurrent_requests = int(
        input(
            "Введите максимальное количество одновременных запросов (на процесс, например, 1000): "
        )
    )
    num_processes = cpu_count()
    output_file = "valid_subdomains.txt"

    print(f"\nНачинаем генерацию и проверку поддоменов для {domain} длиной {length}...\n")
    subdomains = generate_subdomains(length, domain, include_dash=include_dash)

    # Важно: избегаем преобразования генератора в список для больших объемов
    # Вместо этого используем итерируемый подход, однако для multiprocessing требуется знать размеры чанков
    subdomains_list = list(subdomains)

    total_subdomains = len(subdomains_list)
    if total_subdomains == 0:
        print("Нет поддоменов для проверки с указанными параметрами.")
        return

    chunk_size = total_subdomains // num_processes + 1
    subdomains_chunks = list(split_iterable(subdomains_list, chunk_size))

    with open(output_file, "w") as f:
        pass  # Очистка файла перед запуском

    # Запуск процессов
    processes = []
    for i, chunk in enumerate(subdomains_chunks):
        process = Process(
            target=worker_process,
            args=(chunk, max_concurrent_requests, output_file),
            name=f"Worker-{i+1}",
        )
        process.start()
        processes.append(process)
        print(f"Запущен процесс {process.name} с {len(chunk)} поддоменами.")

    for process in processes:
        process.join()

    print("\nПроверка завершена. Результаты сохранены в 'valid_subdomains.txt'.")


if __name__ == "__main__":
    # Очистка файла перед запуском
    with open("valid_subdomains.txt", "w") as f:
        pass
    if sys.platform == "win32":
        import multiprocessing

        multiprocessing.set_start_method("spawn", force=True)

    main()
