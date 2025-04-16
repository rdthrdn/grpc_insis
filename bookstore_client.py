import grpc
import bookstore_pb2
import bookstore_pb2_grpc
from typing import List
import os
import time
import threading
from datetime import datetime
import queue

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

class BookStoreClient:
    def __init__(self):
        self.channel = grpc.insecure_channel('localhost:50051')
        self.stub = bookstore_pb2_grpc.BookStoreStub(self.channel)
        self.username = input("Enter your username: ")
        self.subscription_thread = None
        self.is_subscribed = False
    
    def add_book(self, title: str, author: str, isbn: str, stock: int, price: float) -> tuple[bool, str]:
        request = bookstore_pb2.AddBookRequest(
            title=title,
            author=author,
            isbn=isbn,
            stock=stock,
            price=price
        )
        response = self.stub.AddBook(request)
        return response.success, response.message
    
    def search_books(self, query: str) -> List[bookstore_pb2.Book]:
        request = bookstore_pb2.SearchBookRequest(query=query)
        response = self.stub.SearchBook(request)
        return response.books
    
    def update_stock(self, book_id: str, new_stock: int) -> tuple[bool, str]:
        request = bookstore_pb2.UpdateStockRequest(
            book_id=book_id,
            new_stock=new_stock
        )
        response = self.stub.UpdateStock(request)
        return response.success, response.message
    
    def list_books(self, page: int = 1, page_size: int = 10) -> tuple[List[bookstore_pb2.Book], int, int]:
        request = bookstore_pb2.ListBooksRequest(
            page=page,
            page_size=page_size
        )
        response = self.stub.ListBooks(request)
        return response.books, response.total_books, response.total_pages
    
    def delete_book(self, book_id: str) -> tuple[bool, str]:
        request = bookstore_pb2.DeleteBookRequest(book_id=book_id)
        response = self.stub.DeleteBook(request)
        return response.success, response.message
    
    def subscribe_to_new_books(self, duration_seconds: int):
        if self.is_subscribed:
            print("Already subscribed to new books!")
            return
        
        def subscribe():
            print("Starting subscription...")
            request = bookstore_pb2.SubscribeRequest(duration_seconds=duration_seconds)
            try:
                for book in self.stub.SubscribeToNewBooks(request):
                    print(f"\n[NOTIFICATION] New book added: {book.title} by {book.author}")
                    print("Press Enter to continue...")
            except Exception as e:
                print(f"Subscription ended: {str(e)}")
            finally:
                self.is_subscribed = False
                print("Subscription finished.")
        
        self.is_subscribed = True
        self.subscription_thread = threading.Thread(target=subscribe)
        self.subscription_thread.daemon = True
        self.subscription_thread.start()
        print(f"\nSubscribed to new books for {duration_seconds} seconds...")
        print("You will receive notifications when new books are added.")
        print("You can continue using other features while subscribed.")
        input("\nPress Enter to continue...")
    
    def bulk_add_books(self, books_data: List[tuple]):
        def generate_requests():
            for title, author, isbn, stock, price in books_data:
                yield bookstore_pb2.AddBookRequest(
                    title=title,
                    author=author,
                    isbn=isbn,
                    stock=stock,
                    price=price
                )
        
        response = self.stub.BulkAddBooks(generate_requests())
        return response.success, response.message
    
    def chat(self):
        print("\n=== Chat Room ===")
        print("Connecting to chat server...")

        active_users = []
        try:
            active_users = self.get_active_users()
            if active_users:
                print("\nActive users:", ", ".join(active_users))
            else:
                print("\nNo other users online at the moment.")
        except Exception as e:
            print(f"Error getting active users: {str(e)}")

        print("\nChat instructions:")
        print("- Type a message to send to everyone (group chat)")
        print("- Type 'username: message' to send a private message")
        print("- Type 'exit' to leave the chat\n")

        exit_flag = threading.Event()
        send_queue = queue.Queue()

        def request_stream():
            # Send initial "LISTENING" message
            yield bookstore_pb2.ChatMessage(
                user=self.username,
                message="LISTENING",
                timestamp=int(time.time())
            )
            # Keep yielding messages from send_queue
            while not exit_flag.is_set():
                try:
                    msg = send_queue.get(timeout=0.1)
                    yield msg
                except queue.Empty:
                    continue

        def listen_for_messages(response_iterator):
            try:
                for response in response_iterator:
                    if response.user == self.username:
                        continue
                    if response.user == "SYSTEM":
                        print(f"\n[SYSTEM]: {response.message}")
                    elif response.message.startswith("[PRIVATE] "):
                        print(f"\n[Private from {response.user}]: {response.message[10:]}")
                    else:
                        print(f"\n[{response.user}]: {response.message}")
                    print("You: ", end="", flush=True)
            except Exception as e:
                print(f"\nListen error: {str(e)}")
                exit_flag.set()

        def send_messages():
            try:
                while not exit_flag.is_set():
                    message = input("You: ")
                    if message.lower() == 'exit':
                        exit_flag.set()
                        break
                    if not message.strip():
                        continue

                    target = None
                    display_message = message
                    if ":" in message:
                        parts = message.split(":", 1)
                        if len(parts) > 1 and parts[0].strip() in active_users:
                            target = parts[0].strip()
                            display_message = parts[1].strip()
                            message = f"{target}: [PRIVATE] {display_message}"

                    chat_msg = bookstore_pb2.ChatMessage(
                        user=self.username,
                        message=message,
                        timestamp=int(time.time())
                    )
                    send_queue.put(chat_msg)
            except Exception as e:
                print(f"\nSend error: {str(e)}")
                exit_flag.set()

        response_iterator = self.stub.Chat(request_stream())

        listen_thread = threading.Thread(target=listen_for_messages, args=(response_iterator,))
        listen_thread.daemon = True
        listen_thread.start()

        send_thread = threading.Thread(target=send_messages)
        send_thread.daemon = True
        send_thread.start()

        try:
            while send_thread.is_alive():
                send_thread.join(0.1)
        except KeyboardInterrupt:
            exit_flag.set()
            print("\nExiting chat...")



    def get_active_users(self):        
        try:
            request = bookstore_pb2.ChatMessage(
                user=self.username,
                message="GET_USERS",
                timestamp=int(time.time())
            )
            
            # We'll just send a message and see who responds
            response = self.stub.Chat(iter([request]))
            return [r.user for r in response if r.user != self.username]
        except:
            return []

def print_book(book: bookstore_pb2.Book):
    print(f"ID: {book.id}")
    print(f"Title: {book.title}")
    print(f"Author: {book.author}")
    print(f"ISBN: {book.isbn}")
    print(f"Stock: {book.stock}")
    print(f"Price: ${book.price:.2f}")
    print("-" * 50)

def print_menu():
    clear_screen()
    print("\n=== BookStore Menu ===")
    print("1. Add Book")
    print("2. Search Books")
    print("3. Update Stock")
    print("4. List All Books")
    print("5. Delete Book")
    print("6. Subscribe to New Books")
    print("7. Bulk Add Books")
    print("8. Chat")
    print("9. Exit")
    return input("Choose an option (1-9): ")

def main():
    client = BookStoreClient()
    
    while True:
        choice = print_menu()
        
        if choice == "1":
            clear_screen()
            print("\n=== Add New Book ===")
            title = input("Title: ")
            author = input("Author: ")
            isbn = input("ISBN: ")
            stock = int(input("Stock: "))
            price = float(input("Price: "))
            
            success, message = client.add_book(title, author, isbn, stock, price)
            print(f"\n{message}")
            input("\nPress Enter to continue...")
        
        elif choice == "2":
            clear_screen()
            print("\n=== Search Books ===")
            query = input("Enter search query: ")
            books = client.search_books(query)
            
            if not books:
                print("No books found.")
            else:
                print(f"\nFound {len(books)} book(s):")
                for book in books:
                    print_book(book)
            input("\nPress Enter to continue...")
        
        elif choice == "3":
            clear_screen()
            print("\n=== Update Stock ===")
            books, _, _ = client.list_books()
            if not books:
                print("No books available to update.")
            else:
                print("\nAvailable books:")
                for i, book in enumerate(books, 1):
                    print(f"{i}. {book.title} (ID: {book.id})")
                
                try:
                    book_index = int(input("\nEnter book number: ")) - 1
                    if 0 <= book_index < len(books):
                        new_stock = int(input("Enter new stock: "))
                        success, message = client.update_stock(books[book_index].id, new_stock)
                        print(f"\n{message}")
                    else:
                        print("Invalid book number.")
                except ValueError:
                    print("Please enter a valid number.")
            input("\nPress Enter to continue...")
        
        elif choice == "4":
            clear_screen()
            print("\n=== List All Books ===")
            books, total_books, total_pages = client.list_books()
            
            if not books:
                print("No books available.")
            else:
                print(f"Total books: {total_books}")
                for book in books:
                    print_book(book)
            input("\nPress Enter to continue...")
        
        elif choice == "5":
            clear_screen()
            print("\n=== Delete Book ===")
            books, _, _ = client.list_books()
            if not books:
                print("No books available to delete.")
            else:
                print("\nAvailable books:")
                for i, book in enumerate(books, 1):
                    print(f"{i}. {book.title} (ID: {book.id})")
                
                try:
                    book_index = int(input("\nEnter book number to delete: ")) - 1
                    if 0 <= book_index < len(books):
                        success, message = client.delete_book(books[book_index].id)
                        print(f"\n{message}")
                    else:
                        print("Invalid book number.")
                except ValueError:
                    print("Please enter a valid number.")
            input("\nPress Enter to continue...")
        
        elif choice == "6":
            clear_screen()
            print("\n=== Subscribe to New Books ===")
            if client.is_subscribed:
                print("You are already subscribed to new books!")
            else:
                duration = int(input("Enter subscription duration in seconds: "))
                client.subscribe_to_new_books(duration)
        
        elif choice == "7":
            clear_screen()
            print("\n=== Bulk Add Books ===")
            books_data = []
            while True:
                print("\nEnter book details (or press Enter to finish):")
                title = input("Title: ")
                if not title:
                    break
                author = input("Author: ")
                isbn = input("ISBN: ")
                stock = int(input("Stock: "))
                price = float(input("Price: "))
                books_data.append((title, author, isbn, stock, price))
            
            if books_data:
                success, message = client.bulk_add_books(books_data)
                print(f"\n{message}")
            input("\nPress Enter to continue...")
        
        elif choice == "8":
            clear_screen()
            print("\n=== Chat ===")
            print("Type your messages. Type 'exit' to leave chat.")
            client.chat()
            input("\nPress Enter to continue...")
        
        elif choice == "9":
            clear_screen()
            print("Goodbye!")
            break
        
        else:
            print("Invalid choice. Please try again.")
            input("\nPress Enter to continue...")

if __name__ == '__main__':
    main() 