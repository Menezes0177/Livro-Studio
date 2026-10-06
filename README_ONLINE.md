# LivroStudio V3.5 — Online

O modo online usa Supabase. O plano Free atual inclui banco Postgres de 500 MB, 1 GB de Storage, 5 GB de egress e 50.000 MAU, sujeito aos limites do serviço.

## 1. Criar o projeto
1. Crie um projeto no Supabase.
2. Abra o SQL Editor.
3. Cole e execute `online_schema.sql`.
4. Em Storage, crie um bucket chamado `book-covers` e marque-o como **Public**.
5. Em Authentication > Providers/Email, para facilitar o teste, você pode desativar a confirmação de e-mail. Se mantiver a confirmação, o usuário deverá confirmar o e-mail antes de entrar.

## 2. Pegar as credenciais
No painel do projeto, copie:
- Project URL
- Publishable Key

Use a **Publishable Key**. Nunca coloque `secret`/`service_role` no aplicativo.

## 3. Conectar o LivroStudio
Abra o programa > **Conta** > **CONFIGURAR ONLINE** e cole os dois valores.

Depois crie uma conta ou entre.

## 4. Teste real entre duas contas
### Conta A
- Entre com o usuário A.
- Vá em Criar.
- Preencha título, autor, sinopse e capa.
- Escolha `Público — Explorer`.
- Publique.

### Conta B
- Abra o LivroStudio em outra máquina ou faça logout e entre com B.
- Abra Explorer.
- O livro da conta A deverá aparecer.
- `Ler` abre o livro diretamente do servidor.
- `+ Biblioteca` baixa uma cópia local e registra o livro na biblioteca online da conta B.

## Segurança
O aplicativo usa somente a chave pública/publishable. A proteção real vem das políticas RLS do `online_schema.sql`: usuários só podem publicar/editar seus próprios livros e só podem alterar sua própria biblioteca.
