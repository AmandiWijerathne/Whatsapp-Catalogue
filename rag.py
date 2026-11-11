"""Shared RAG query pipeline for the Streamlit app and WhatsApp webhook."""

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    GoogleGenerativeAIEmbeddings,
)
from langchain_google_genai.chat_models import GoogleRateLimitError

from whatsapp_backend.config import FAISS_INDEX_PATH, GOOGLE_API_KEY


def _invoke_chat_model(prompt: str) -> object:
    try:
        return ChatGoogleGenerativeAI(
            model="gemini-3.6-flash",
            google_api_key=GOOGLE_API_KEY,
        ).invoke(prompt, automatic_function_calling={"disable": True})
    except GoogleRateLimitError:
        try:
            return ChatGoogleGenerativeAI(
                model="gemini-3.5-flash",
                google_api_key=GOOGLE_API_KEY,
                temperature=0,
            ).invoke(prompt, automatic_function_calling={"disable": True})
        except GoogleRateLimitError as error:
            raise RuntimeError(
                "Gemini rate limits have been reached for both the primary and "
                "fallback models. Try again after the quota resets or use a "
                "Google API project with available quota."
            ) from error


def _create_embeddings() -> GoogleGenerativeAIEmbeddings:
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is not configured")
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GOOGLE_API_KEY,
    )


def _load_vector_store() -> FAISS:
    if not (FAISS_INDEX_PATH / "index.faiss").is_file():
        raise RuntimeError(
            f"No saved PDF index found at {FAISS_INDEX_PATH}. "
            "Upload and process PDFs in the Streamlit app first."
        )

    return FAISS.load_local(
        str(FAISS_INDEX_PATH),
        _create_embeddings(),
        allow_dangerous_deserialization=True,
    )


def _extract_answer_text(response: object) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    text_parts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n".join(text_parts)


def query_rag_with_sources(
    question: str,
    vector_store: FAISS | None = None,
) -> tuple[str, list[Document]]:
    """Answer a question and return the retrieved documents."""
    if not question.strip():
        raise ValueError("Question must not be empty")

    if vector_store is None:
        vector_store = _load_vector_store()

    relevant_documents = vector_store.similarity_search(question, k=4)
    context = "\n\n".join(
        (
            f"Source: {document.metadata.get('source', 'Unknown')}, "
            f"Page: {document.metadata.get('page', 'Unknown')}\n"
            f"{document.page_content}"
        )
        for document in relevant_documents
    )
    prompt = f"""
You are a PDF question-answering assistant.

Answer the question using only the provided PDF context.

If the answer cannot be found in the context, say:
"The answer is not available in the uploaded PDFs."

Context:
{context}

Question:
{question}

Give a clear and concise answer.
"""

    response = _invoke_chat_model(prompt)
    return _extract_answer_text(response), relevant_documents


def query_rag(question: str, vector_store: FAISS | None = None) -> str:
    """Answer a question from the saved PDF index or a provided index."""

    answer, _ = query_rag_with_sources(question, vector_store)
    return answer
