"""Executa a validação centralizada da tabela relation."""
import argparse

from quality import common
from quality.relation import validate


def positive_sample_size(value: str) -> int:
    try:
        sample_size = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("o tamanho da amostra deve ser um inteiro positivo") from exc
    if sample_size < 1:
        raise argparse.ArgumentTypeError("o tamanho da amostra deve ser maior que zero")
    return sample_size


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=positive_sample_size,
                        help="Validar uma amostra repetível deste tamanho; padrão: todas as relações")
    args = parser.parse_args()
    scores, errors, metadata = validate(sample_size=args.sample_size)
    paths = common.save_validation_results("relations", scores, errors, metadata)
    print(f"Validação de relation concluída: {len(scores)} regras, {len(errors)} ocorrências inválidas.")
    for key, path in paths.items():
        print(f"{key}: {path}")
