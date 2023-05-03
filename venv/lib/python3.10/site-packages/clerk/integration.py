from masonite.packages import create_or_append_config
import os

package_directory = os.path.dirname(os.path.realpath(__file__))

def boot():
    create_or_append_config(os.path.join(package_directory, 'snippets/configs/payment.py'))
