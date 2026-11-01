"""Executa a validação centralizada da tabela relation."""
from quality import common
from quality.relation import validate

if __name__ == "__main__":
    scores, errors, metadata = validate()
    paths = common.save_validation_results("relations", scores, errors, metadata)
    print(f"Validação de relation concluída: {len(scores)} regras, {len(errors)} ocorrências inválidas.")
    for key, path in paths.items():
        print(f"{key}: {path}")
