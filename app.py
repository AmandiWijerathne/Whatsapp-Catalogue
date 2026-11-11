import pymupdf
import streamlit as st
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from currency import answer_currency_question
from rag import query_rag_with_sources
from whatsapp_backend.config import FAISS_INDEX_PATH, GOOGLE_API_KEY


# Configure the Streamlit page
st.set_page_config(
    page_title="PDF RAG System",
    page_icon="📚",
)

st.title("📚 PDF RAG System")
st.write(
    "Upload PDF files and ask questions based on their content."
)


# Stop the application if the API key is missing
if not GOOGLE_API_KEY:
    st.error(
        "GOOGLE_API_KEY was not found in the .env file."
    )
    st.stop()

# if GOOGLE_API_KEY.startswith(("AQ.", "ya29.")):
#    st.error(
#       "GOOGLE_API_KEY is an OAuth access token, not a Gemini API key. "
#       "Create a Gemini API key in Google AI Studio, replace GOOGLE_API_KEY "
#       "in the project .env file, and restart the app."
#    )
 #   st.stop()*\


def extract_documents(uploaded_files):
    """Extract text and metadata from uploaded PDF files."""

    documents = []

    for uploaded_file in uploaded_files:
        pdf_bytes = uploaded_file.getvalue()

        pdf = pymupdf.open(
            stream=pdf_bytes,
            filetype="pdf",
        )

        for page_number, page in enumerate(pdf):
            text = page.get_text()

            if text.strip():
                document = Document(
                    page_content=text,
                    metadata={
                        "source": uploaded_file.name,
                        "page": page_number + 1,
                    },
                )

                documents.append(document)

        pdf.close()

    return documents


def create_vector_store(documents):
    """Split documents, create embeddings, and build FAISS index."""

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
    )

    chunks = text_splitter.split_documents(documents)

    embeddings = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=GOOGLE_API_KEY,
    )

    vector_store = FAISS.from_documents(
        chunks,
        embeddings,
    )
    FAISS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    vector_store.save_local(str(FAISS_INDEX_PATH))

    return vector_store


# PDF upload section
uploaded_files = st.file_uploader(
    "Upload PDF files",
    type=["pdf"],
    accept_multiple_files=True,
)


# Process PDFs when new files are uploaded
if uploaded_files:
    file_signature = tuple(
        (uploaded_file.name, uploaded_file.size)
        for uploaded_file in uploaded_files
    )

    if (
        st.session_state.get("file_signature")
        != file_signature
    ):
        try:
            with st.spinner(
                "Reading and indexing PDFs..."
            ):
                documents = extract_documents(
                    uploaded_files
                )

                if not documents:
                    st.error(
                        "No readable text was found "
                        "in the uploaded PDFs."
                    )
                    st.stop()

                vector_store = create_vector_store(
                    documents
                )

                st.session_state.vector_store = (
                    vector_store
                )
                st.session_state.file_signature = (
                    file_signature
                )

            st.success("PDF processing completed!")

        except Exception as error:
            error_message = str(error)
            if (
                "api_key_invalid" in error_message.lower()
                or "api key not valid" in error_message.lower()
            ):
                st.error(
                    "Google rejected GOOGLE_API_KEY as invalid. Create a Gemini "
                    "API key in Google AI Studio "
                    "(https://aistudio.google.com/app/apikey), replace "
                    "GOOGLE_API_KEY in the project .env file, and restart "
                    "Streamlit. Do not use an OAuth or Meta access token."
                )
            elif (
                "getaddrinfo failed" in error_message.lower()
                or "11001" in error_message
            ):
                st.error(
                    "Could not resolve Google's API hostname. Check that this "
                    "computer has internet access and that DNS, VPN, firewall, "
                    "or proxy settings allow connections to "
                    "generativelanguage.googleapis.com, then retry. On Windows, "
                    "you can check DNS with `nslookup "
                    "generativelanguage.googleapis.com`. If DNS now works, "
                    "restart Streamlit and upload the PDF again."
                )
            else:
                st.error(f"PDF processing failed: {error}")
            st.stop()


# Question input
question = st.text_input(
    "Ask a question about the PDFs"
)


# Route currency questions directly; otherwise use the PDF RAG pipeline.
if question:
    try:
        currency_answer = answer_currency_question(question)
        if currency_answer:
            st.subheader("Answer")
            st.markdown(currency_answer)
        elif "vector_store" in st.session_state:
            with st.spinner("Finding the answer..."):
                answer, relevant_documents = query_rag_with_sources(
                    question,
                    vector_store=st.session_state.vector_store,
                )

            st.subheader("Answer")

            if answer.strip():
                st.markdown(answer)
            else:
                st.warning(
                    "Gemini did not return a readable answer."
                )

            with st.expander("Sources"):
                for document in relevant_documents:
                    source = document.metadata["source"]
                    page = document.metadata["page"]

                    st.write(
                        f"- {source} — Page {page}"
                    )
        else:
            st.warning(
                "Please upload and process a PDF first."
            )

    except Exception as error:
        st.error(
            f"Answer generation failed: {error}"
        )
